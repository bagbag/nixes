{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.services.librechat;
in
{
  options.modules.services.librechat = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable LibreChat service.";
    };

    mongoUri = lib.mkOption {
      type = lib.types.str;
      default = "mongodb://localhost:27017/librechat";
      description = "MongoDB URI for LibreChat.";
    };

    allowRegistration = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Allow user registration.";
    };

    googleServiceKeyFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Path to Google service key file.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.librechat = {
      enable = true;
      credentialsFile = "/var/lib/librechat/secrets";

      env = {
        MONGO_URI = cfg.mongoUri;
        ALLOW_REGISTRATION = if cfg.allowRegistration then "true" else "false";
        ALLOW_EMAIL_LOGIN = "true";
        SESSION_EXPIRY = toString (1000 * 60 * 60 * 24 * 365);
        REFRESH_TOKEN_EXPIRY = toString (1000 * 60 * 60 * 24 * 365);

        GOOGLE_SERVICE_KEY_FILE = lib.mkIf (cfg.googleServiceKeyFile != null) cfg.googleServiceKeyFile;
        GOOGLE_CLOUD_LOCATION = "eu-west4";
      };

      settings = {
        endpoints = {
          google = {
            models = {
              vertex = true;
              default = [
                "gemini-3-pro-preview"
                "gemini-3-flash-preview"
                "gemini-2.5-pro"
                "gemini-2.5-flash"
              ];
            };
          };
        };
      };
    };

    systemd.services.librechat-secrets-generator = {
      description = "Generate secrets for LibreChat";
      wantedBy = [ "multi-user.target" ];
      before = [ "librechat.service" ];

      path = [ pkgs.openssl ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = config.services.librechat.user;
        Group = config.services.librechat.group;
        StateDirectory = "librechat";
        StateDirectoryMode = "0700";
      };

      script = ''
        SECRET_FILE="/var/lib/librechat/secrets"

        if [ ! -f "$SECRET_FILE" ]; then
          echo "Generating LibreChat secrets..."
          CREDS_KEY=$(openssl rand -hex 32)
          CREDS_IV=$(openssl rand -hex 16)
          JWT_SECRET=$(openssl rand -hex 32)
          JWT_REFRESH_SECRET=$(openssl rand -hex 32)

          cat <<EOF > "$SECRET_FILE"
        CREDS_KEY=$CREDS_KEY
        CREDS_IV=$CREDS_IV
        JWT_SECRET=$JWT_SECRET
        JWT_REFRESH_SECRET=$JWT_REFRESH_SECRET
        EOF

          chmod 600 "$SECRET_FILE"
        fi
      '';
    };
  };
}

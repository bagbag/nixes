{ config, pkgs, ... }:
let
  secretFile = "/var/lib/librechat/secrets";
in
{
  services.librechat = {
    enable = true;
    credentialsFile = secretFile;

    env = {
      MONGO_URI = "mongodb://localhost:27017/librechat";
      ALLOW_REGISTRATION = true;
      ALLOW_EMAIL_LOGIN = true;
      SESSION_EXPIRY = 1000 * 60 * 60 * 24 * 365;
      REFRESH_TOKEN_EXPIRY = 1000 * 60 * 60 * 24 * 365;

      GOOGLE_SERVICE_KEY_FILE = "/var/lib/librechat/google-insolytix-application-service-key.json";
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
            SECRET_FILE="${secretFile}"

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
}

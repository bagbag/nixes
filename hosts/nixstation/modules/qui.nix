{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.services.qui;
  secretFile = "/var/lib/qui/secret";
in
{
  options.modules.services.qui.enable = lib.mkEnableOption "qui";

  config = lib.mkIf cfg.enable {
    services.qui.enable = true;
    services.qui.secretFile = secretFile;

    systemd.services.qui-secret-generator = {
      description = "Generate session secret for qui";
      wantedBy = [ "multi-user.target" ];
      before = [ "qui.service" ];

      path = [ pkgs.openssl ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };

      script = ''
        if [ ! -f "${secretFile}" ]; then
          mkdir -p "$(dirname "${secretFile}")"
          openssl rand -hex 32 > "${secretFile}"
          chmod 600 "${secretFile}"
        fi
      '';
    };

    systemd.services.qui = {
      after = [ "qui-secret-generator.service" ];
      requires = [ "qui-secret-generator.service" ];
    };
  };
}

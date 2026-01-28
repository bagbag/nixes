{
  config,
  lib,
  ...
}:
let
  cfg = config.modules.system;
in
{
  options.modules.system = {
    type = lib.mkOption {
      type = lib.types.enum [
        "desktop"
        "server"
      ];
      default = "server";
      description = "The type of system (desktop or server), used to set sensible defaults.";
    };

    installMode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable installation mode (disables heavy packages like chromium, texlive, etc.).";
    };
  };
}

{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.services.ollama;

  # Acceleration is configured by selecting a package (per the NixOS wiki),
  # not via the deprecated `services.ollama.acceleration` option.
  accelerationPackages = {
    rocm = pkgs.ollama-rocm; # most modern AMD GPUs
    cuda = pkgs.ollama-cuda; # most modern NVIDIA GPUs
    vulkan = pkgs.ollama-vulkan; # most modern GPUs on Linux
    cpu = pkgs.ollama-cpu; # CPU only
  };
in
{
  options.modules.services.ollama = {
    enable = lib.mkEnableOption "Ollama LLM service";

    acceleration = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum (lib.attrNames accelerationPackages));
      default = null;
      example = "rocm";
      description = ''
        GPU acceleration backend. Selects the matching ollama package,
        e.g. "rocm" uses {option}`pkgs.ollama-rocm`. When null the plain
        `pkgs.ollama` package is used.
      '';
    };

    loadModels = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [
        "llama3.2:3b"
        "deepseek-r1:1.5b"
      ];
      description = "Models to download/preload when the service starts. See https://ollama.com/library";
    };
  };

  config = lib.mkIf cfg.enable {
    services.ollama = {
      enable = true;
      package = if cfg.acceleration == null then pkgs.ollama else accelerationPackages.${cfg.acceleration};
      loadModels = cfg.loadModels;
    };

    # Work around a boot-time race where ollama starts before the GPU kernel
    # driver (e.g. amdgpu) is loaded, so GPU discovery finds nothing and the
    # service silently falls back to CPU until manually restarted.
    # Ordering after systemd-modules-load ensures the driver is up first.
    # See https://github.com/NixOS/nixpkgs/issues/419097 (fix PR #422355).
    systemd.services.ollama.after = [ "systemd-modules-load.service" ];
  };
}

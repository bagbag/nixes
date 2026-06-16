{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.modules.services.llama-swap;

  # Acceleration selects the matching llama-cpp build flag, mirroring the
  # approach used for the ollama module.
  acceleratedPackage =
    if cfg.acceleration == "rocm" then
      pkgs.llama-cpp.override { rocmSupport = true; } # most modern AMD GPUs
    else if cfg.acceleration == "cuda" then
      pkgs.llama-cpp.override { cudaSupport = true; } # most modern NVIDIA GPUs
    else if cfg.acceleration == "vulkan" then
      pkgs.llama-cpp.override { vulkanSupport = true; } # most modern GPUs on Linux
    else
      pkgs.llama-cpp; # CPU only

  # Binary that each model's `cmd` invokes. Exposed so model definitions only
  # need to supply a GGUF path and extra flags, not the server path.
  llamaServer = lib.getExe' cfg.package "llama-server";
in
{
  options.modules.services.llama-swap = {
    enable = lib.mkEnableOption "llama-swap (llama.cpp model swapping proxy)";

    acceleration = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [
        "rocm"
        "cuda"
        "vulkan"
        "cpu"
      ]);
      default = null;
      example = "rocm";
      description = ''
        GPU acceleration backend for the bundled llama-cpp build. Selects the
        matching llama-cpp override flag, e.g. "rocm" builds with
        `rocmSupport = true`. When null (or "cpu") the plain CPU build is used.
      '';
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = acceleratedPackage;
      defaultText = lib.literalExpression "pkgs.llama-cpp (with the selected acceleration override)";
      description = ''
        The llama-cpp package providing `llama-server`. Defaults to a build
        matching {option}`acceleration`; override to pin a custom package.
      '';
    };

    listenAddress = lib.mkOption {
      type = lib.types.str;
      default = "localhost";
      example = "0.0.0.0";
      description = "Address that llama-swap listens on.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Port that llama-swap listens on.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Whether to open {option}`port` in the firewall.";
    };

    healthCheckTimeout = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 60;
      description = "Seconds llama-swap waits for a model to become healthy after launch.";
    };

    hfTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      example = "/run/agenix/hf-token";
      description = ''
        Optional path to a file passed to the unit as an `EnvironmentFile`,
        used to authenticate Hugging Face downloads for gated/private repos.
        The file must contain a line like `HF_TOKEN=hf_...`.
      '';
    };

    models = lib.mkOption {
      default = { };
      description = ''
        High-level model definitions. Each entry is turned into a
        `services.llama-swap.settings.models.<name>` block whose `cmd` runs the
        bundled `llama-server`. Supply either {option}`hfRepo` to auto-download
        the GGUF from Hugging Face on first launch, or {option}`modelPath` to
        point at a local file (exactly one). For full control use
        {option}`settings` instead.
      '';
      example = lib.literalExpression ''
        {
          "qwen3-4b" = {
            hfRepo = "unsloth/Qwen3-4B-GGUF:Q4_K_M";
            extraArgs = "-ngl 99 -c 8192 --no-webui";
            aliases = [ "default" ];
          };
        }
      '';
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            hfRepo = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              example = "unsloth/Qwen3-4B-GGUF:Q4_K_M";
              description = ''
                Hugging Face repo (optionally `:quant`) passed to `llama-server -hf`.
                The GGUF is downloaded on the model's first launch and cached under
                {file}`/var/lib/llama-swap` (see `LLAMA_CACHE`). Mutually exclusive
                with {option}`modelPath`.
              '';
            };

            modelPath = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              example = "/var/lib/llama-swap/models/model.gguf";
              description = ''
                Path to a local GGUF file passed to `llama-server -m`. Mutually
                exclusive with {option}`hfRepo`.
              '';
            };

            extraArgs = lib.mkOption {
              type = lib.types.separatedString " ";
              default = "-ngl 99 --no-webui";
              description = "Extra flags appended to the `llama-server` command line.";
            };

            aliases = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              description = "Alternative model names that resolve to this model.";
            };
          };
        }
      );
    };

    settings = lib.mkOption {
      type = lib.types.attrs;
      default = { };
      description = ''
        Additional llama-swap configuration merged into the generated config.
        Refer to the [example configuration](https://github.com/mostlygeek/llama-swap/blob/main/config.example.yaml).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = lib.mapAttrsToList (name: m: {
      assertion = (m.hfRepo != null) != (m.modelPath != null);
      message = "modules.services.llama-swap.models.${name}: set exactly one of hfRepo or modelPath.";
    }) cfg.models;

    services.llama-swap = {
      enable = true;
      inherit (cfg)
        listenAddress
        port
        openFirewall
        ;
      settings = lib.mkMerge [
        {
          healthCheckTimeout = cfg.healthCheckTimeout;
          models = lib.mapAttrs (
            _name: m:
            let
              modelArg = if m.hfRepo != null then "-hf ${m.hfRepo}" else "-m ${m.modelPath}";
            in
            {
              cmd = "${llamaServer} --port \${PORT} ${modelArg} ${m.extraArgs}";
              aliases = m.aliases;
            }
          ) cfg.models;
        }
        cfg.settings
      ];
    };

    systemd.services.llama-swap = {
      # Same boot-time GPU race as ollama: ensure the kernel driver (e.g.
      # amdgpu) is loaded before llama-swap launches a server, otherwise GPU
      # discovery fails and it silently falls back to CPU.
      after = lib.mkIf (cfg.acceleration != null && cfg.acceleration != "cpu") [
        "systemd-modules-load.service"
      ];

      # The upstream unit runs as a hardened DynamicUser with
      # ProtectSystem=strict and no writable state, so `-hf` downloads have
      # nowhere persistent to land. A StateDirectory (exempt from the strict
      # read-only filesystem) plus LLAMA_CACHE gives llama.cpp a durable cache
      # so each model is fetched from Hugging Face only once.
      serviceConfig = {
        StateDirectory = "llama-swap";
        EnvironmentFile = lib.mkIf (cfg.hfTokenFile != null) cfg.hfTokenFile;
      };
      environment.LLAMA_CACHE = "/var/lib/llama-swap";
    };
  };
}

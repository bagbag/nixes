{ inputs, lib, ... }:
let
  codexHosts = [
    "macbook-pro"
    "nixbook-air"
    "nixmobil"
    "nixstation"
  ];

  codexConfigModule = {
    environment.etc."codex/config.toml".source =
      inputs.self.outPath + "/home/patrick/codex/config.toml";
  };
in
{
  nstdl.hosts = lib.genAttrs codexHosts (_: {
    extraModules = [ codexConfigModule ];
  });
}

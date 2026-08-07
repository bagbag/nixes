{
  description = "Nixos Configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Temporary: Node 26.7.0 is not yet substituted for aarch64-darwin.
    # Keep Node 26 on the latest verified cached unstable revision; remove this
    # input and ./modules/flake-parts/workarounds.nix once the regular cache catches up.
    nixpkgs-nodejs.url = "github:NixOS/nixpkgs/e72e4f299401a3689d4b3d5fc6496b11db7064eb";

    nixos-hardware.url = "github:NixOS/nixos-hardware/master";

    flake-parts.url = "github:hercules-ci/flake-parts";

    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";

    nix-vscode-extensions.url = "github:nix-community/nix-vscode-extensions";
    nix-vscode-extensions.inputs.nixpkgs.follows = "nixpkgs";

    nstdl = {
      url = "github:bagbag/nstdl";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-parts.follows = "flake-parts";
      inputs.disko.follows = "disko";
    };
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [
        inputs.nstdl.flakeModules.default
        ./modules/flake-parts/workarounds.nix
        ./modules/flake-parts/secrets.nix
        ./modules/flake-parts/nixstation.nix
        ./modules/flake-parts/nixmobil.nix
        ./modules/flake-parts/nixbook-air.nix
        ./modules/flake-parts/macbook-pro.nix
      ];
    };
}

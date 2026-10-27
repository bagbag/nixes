{
  description = "Nixos Configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Node 26 substitutes for aarch64-darwin regularly lag nixpkgs. Advance
    # this separate pin only after verifying the full package is cached;
    # ./update-nodejs-pin.sh does both.
    nixpkgs-nodejs.url = "github:NixOS/nixpkgs/3ec636362e1816bc2f0888fa0fa2c69f1bc9e504";

    nixos-hardware.url = "github:NixOS/nixos-hardware/master";
    nixos-hardware.inputs.nixpkgs.follows = "nixpkgs";

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
        ./accounts.nix
        ./secrets/default.nix
        ./hosts/nixstation/default.nix
        ./hosts/nixmobil/default.nix
        ./hosts/nixbook-air/default.nix
        ./hosts/macbook-pro/default.nix
        ./hosts/macbook-pro-nixvm/default.nix
        ./modules/flake-parts/workarounds.nix
        ./modules/flake-parts/codex.nix
      ];
    };
}

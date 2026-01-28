{
  description = "Nixos Configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    nixos-hardware.url = "github:NixOS/nixos-hardware/master";

    flake-parts.url = "github:hercules-ci/flake-parts";

    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";

    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    nix-index-database.url = "github:nix-community/nix-index-database";
    nix-index-database.inputs.nixpkgs.follows = "nixpkgs";

    nix-vscode-extensions.url = "github:nix-community/nix-vscode-extensions";
    nix-vscode-extensions.inputs.nixpkgs.follows = "nixpkgs";

    stylix.url = "github:nix-community/stylix";
    stylix.inputs.nixpkgs.follows = "nixpkgs";

    agenix-rekey.url = "github:oddlama/agenix-rekey";
    agenix-rekey.inputs.nixpkgs.follows = "nixpkgs";

    ragenix.url = "github:yaxitech/ragenix";
    ragenix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    inputs@{ flake-parts, nixpkgs, ... }:
    let
      lib = nixpkgs.lib;
    in
    flake-parts.lib.mkFlake { inherit inputs; } {
      imports = [
        inputs.agenix-rekey.flakeModule
      ];

      systems = [
        "x86_64-linux"
      ];

      perSystem =
        {
          config,
          self',
          inputs',
          pkgs,
          system,
          ...
        }:
        {
          packages.default = pkgs.hello; # Placeholder
          packages.ragenix = inputs.ragenix.packages.${system}.default;
          packages.diff-gen = pkgs.callPackage ./pkgs/diff-gen/default.nix { };

          devShells.default = pkgs.mkShell {
            nativeBuildInputs = [ config.agenix-rekey.package ];
          };
        };

      flake = {
        overlays.default = final: prev: {
          nstdl = {
            diff-gen = final.callPackage ./pkgs/diff-gen/default.nix { };
          };
        };

        nixosModules = import ./modules/default.nix;

        nixosConfigurations = {
          nixstation = inputs.nixpkgs.lib.nixosSystem {
            system = "x86_64-linux";
            specialArgs = { inherit inputs; };
            modules = (lib.attrValues inputs.self.nixosModules) ++ [
              ./hosts/nixstation/host.nix

              inputs.stylix.nixosModules.stylix
              inputs.ragenix.nixosModules.default
              inputs.agenix-rekey.nixosModules.default

              # Overlays
              {
                nixpkgs.overlays = [
                  inputs.nix-vscode-extensions.overlays.default
                  inputs.self.overlays.default
                ];
              }
            ];
          };

          nixmobil = inputs.nixpkgs.lib.nixosSystem {
            system = "x86_64-linux";
            specialArgs = { inherit inputs; };
            modules = (lib.attrValues inputs.self.nixosModules) ++ [
              ./hosts/nixmobil/host.nix

              inputs.stylix.nixosModules.stylix
              inputs.ragenix.nixosModules.default
              inputs.agenix-rekey.nixosModules.default

              # Overlays
              {
                nixpkgs.overlays = [
                  inputs.nix-vscode-extensions.overlays.default
                  inputs.self.overlays.default
                ];
              }
            ];
          };
        };
      };
    };
}

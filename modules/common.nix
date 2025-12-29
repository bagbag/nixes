{ inputs, ... }:
{
  imports = [
    inputs.disko.nixosModules.disko

    ./administration.nix
    ./base.nix
    ./firewall.nix
    ./home-manager.nix
    ./network.nix
    ./nix.nix
    ./podman.nix
    ./programs.nix
    ./services.nix
    ./system-packages.nix
  ];
}

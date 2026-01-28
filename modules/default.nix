{
  base = ./base.nix;
  common = ./common.nix;
  administration = ./administration.nix;
  desktop = ./desktop.nix;
  firewall = ./firewall.nix;
  amd = ./hardware/amd.nix;
  spdifWorkaround = ./hardware/spdif-workaround.nix;
  homeManager = ./home-manager.nix;
  network = ./network.nix;
  nix = ./nix.nix;
  podman = ./podman.nix;
  programs = ./programs.nix;
  system = ./system.nix;
  systemPackages = ./system-packages.nix;
  user = ./user.nix;

  # Services
  librechat = ./services/librechat.nix;
  mongodb = ./services/mongodb.nix;
  syncthing = ./services/syncthing.nix;
}

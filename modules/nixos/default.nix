{
  base = ./base.nix;
  common = ./common.nix;
  administration = ./administration.nix;
  desktop = ./desktop.nix;
  firewall = ./firewall.nix;
  amd = ./hardware/amd.nix;
  intel = ./hardware/intel.nix;
  laptop = ./hardware/laptop.nix;
  spdifWorkaround = ./hardware/spdif-workaround.nix;
  homeManager = ./home-manager.nix;
  network = ./network.nix;
  nix = ../shared/nix.nix;
  podman = ./podman.nix;
  programs = ./programs.nix;
  system = ../shared/system.nix;
  installMode = ./install-mode.nix;
  systemPackages = ./system-packages.nix;
  user = ./user.nix;

  # Services
  librechat = ./services/librechat.nix;
  mongodb = ./services/mongodb.nix;
  syncthing = ../shared/services/syncthing-options.nix;
}

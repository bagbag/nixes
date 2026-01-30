{
  common = ./common.nix;
  user = ./user.nix;
  programs = ./programs.nix;
  homeManager = ./home-manager.nix;
  nix = ./nix.nix;

  system = ../shared/system.nix;

  # Services
  syncthing = ../shared/services/syncthing-options.nix;
}

{
  system = ./system.nix;
  programs = ./programs.nix;
  nix = ./nix.nix;
  systemPackages = ./system-packages.nix;

  # Home Manager Modules
  home = ./home/home.nix;
  shell = ./home/shell.nix;

  # Services
  openssh = ./services/openssh.nix;
  syncthing = ./home/services/syncthing.nix;
  syncthing-options = ./services/syncthing-options.nix;
}

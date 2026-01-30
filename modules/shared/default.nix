{
  system = ./system.nix;
  
  # Home Manager Modules
  home = ./home/home.nix;
  shell = ./home/shell.nix;
  
  # Services
  syncthing = ./services/syncthing.nix;
  syncthing-options = ./services/syncthing-options.nix;
}
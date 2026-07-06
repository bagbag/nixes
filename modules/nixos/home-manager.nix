{ inputs, ... }:
{
  imports = [
    inputs.home-manager.nixosModules.home-manager
  ];

  home-manager = {
    useGlobalPkgs = true;
    useUserPackages = true;
    # backupFileExtension = "backup"; # unset: error out on file collisions instead of backing up
    extraSpecialArgs = { inherit inputs; };
    sharedModules = [
      inputs.nix-index-database.homeModules.nix-index
    ];
  };
}

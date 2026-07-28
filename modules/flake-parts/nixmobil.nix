{ inputs, ... }:
{
  nstdl.hosts.nixmobil = {
    platform = "nixos";
    system = "x86_64-linux";
    role = "workstation";
    features = [
      "developer"
      "desktop-apps"
      "podman"
      "remote-access"
      "secrets"
      "full-stack-developer"
      "remote-desktop"
      "office-suite"
      "intel"
      "laptop"
    ];
    systemStateVersion = "25.11";
    domain = "lan";
    secrets.hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHBJaMs/1fLo7FOQD5xTHc7Pox4rHN5G6hX96P81DO4e";
    accounts = {
      primary = "patrick";
      users.patrick = {
        administrator = true;
        home = {
          enable = true;
          stateVersion = "25.11";
          features = [
            "workstation"
            "developer"
            "system-utilities"
            "desktop-apps"
            "full-stack-developer"
            "office-tools"
            "document-tools"
            "creative-media"
            "remote-desktop"
            "messaging"
            "gnome-extras"
            "vscode"
            "ai-agent-tools"
            "secret-admin"
          ];
        };
      };
    };
    extraModules = [
      { nixpkgs.overlays = [ inputs.nix-vscode-extensions.overlays.default ]; }
      inputs.disko.nixosModules.disko
      inputs.nixos-hardware.nixosModules.common-cpu-intel
      inputs.nixos-hardware.nixosModules.common-pc-laptop
      inputs.nixos-hardware.nixosModules.common-pc-laptop-ssd
      (inputs.self.outPath + "/hosts/nixmobil/hardware-configuration.nix")
      (inputs.self.outPath + "/hosts/nixmobil/disko.nix")
      {
        home-manager.users.patrick.imports = [
          (inputs.self.outPath + "/modules/shared/home/patrick.nix")
        ];
      }
      (inputs.self.outPath + "/hosts/nixmobil/nstdl.nix")
    ];
  };
}

{ inputs, ... }:
{
  nstdl = {
    accounts.people.patrick.sshKeys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMM/o1cLFjnD1m41DE41yWySYzOjvN7MizVJLIpbhbXN patrick@nixstation"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvnCyc7hK0Tb5bXujzcjF+FjpmGi4FnfD9y84RtU6ZQ patrick@nixmobil"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBAZNTeHlIEMl2ILVsUjmWwptaTSSLOQRx0Xpeci562a patrick@nixbook-air"
    ];

    hosts.nixstation = {
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
      ];
      systemStateVersion = "25.11";
      domain = "lan";
      secrets.hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFALQ9WJhksoUBKzZGwx2xN0Y6sb/1BEX4/j+PsdI3Cx";
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
              "desktop-apps"
              "full-stack-developer"
              "office-tools"
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
        inputs.nixos-hardware.nixosModules.common-cpu-amd
        inputs.nixos-hardware.nixosModules.common-cpu-amd-pstate
        inputs.nixos-hardware.nixosModules.common-pc-ssd
        inputs.self.nixosModules.llama-swap
        inputs.self.nixosModules.ollama
        inputs.self.nixosModules.qui
        (inputs.self.outPath + "/hosts/nixstation/hardware-configuration.nix")
        (inputs.self.outPath + "/hosts/nixstation/disko.nix")
        {
          home-manager.users.patrick.imports = [
            (inputs.self.outPath + "/modules/shared/home/patrick.nix")
          ];
        }
        (inputs.self.outPath + "/hosts/nixstation/nstdl.nix")
      ];
    };
  };
}

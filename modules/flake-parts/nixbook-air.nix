{ inputs, ... }:
{
  nstdl.hosts.nixbook-air = {
    platform = "darwin";
    system = "aarch64-darwin";
    role = "workstation";
    features = [
      "developer"
      "desktop-apps"
      "podman"
      "remote-access"
      "secrets"
      "office-suite"
    ];
    systemStateVersion = 6;
    secrets.hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPpPhXfy+OmQXWkjhFxn68tDs+++MTXzpSgMS3iM5gwN";
    accounts = {
      primary = "patrick";
      users.patrick.home = {
        enable = true;
        stateVersion = "25.11";
        features = [
          "workstation"
          "developer"
          "desktop-apps"
          "full-stack-developer"
          "messaging"
          "syncthing"
          "document-tools"
          "vscode"
          "ai-agent-tools"
          "secret-admin"
        ];
      };
    };
    extraModules = [
      { nixpkgs.overlays = [ inputs.nix-vscode-extensions.overlays.default ]; }
      {
        system.configurationRevision = inputs.self.rev or inputs.self.dirtyRev or null;
        environment.variables.NH_FLAKE = "/etc/nix-darwin";
      }
      {
        home-manager.users.patrick.imports = [
          (inputs.self.outPath + "/modules/shared/home/patrick.nix")
        ];
      }
      (inputs.self.outPath + "/hosts/nixbook-air/nstdl.nix")
    ];
  };
}

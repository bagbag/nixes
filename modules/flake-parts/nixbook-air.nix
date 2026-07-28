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
      "secrets"
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

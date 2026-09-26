{ inputs, ... }:
{
  nstdl.hosts.macbook-pro-nixvm = {
    platform = "nixos";
    system = "aarch64-linux";
    role = "workstation";
    features = [
      "developer"
      "desktop-apps"
      "podman"
      "remote-access"
      "secrets"
    ];
    virtualization = "qemu";
    systemStateVersion = "25.11";
    domain = "lan";
    secrets.hostPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFLl54cxAbniq49XaXyNTXWUv1uORPuQnYbq09I3COoM root@macbook-pro-nixvm";
    storage = {
      device = "/dev/vda";
      encryption = "none";
    };
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
            "gnome-extras"
            "syncthing"
            "secret-admin"
          ];
        };
      };
    };
    extraModules = [
      (inputs.self.outPath + "/hosts/macbook-pro-nixvm/desktop.nix")
      (inputs.self.outPath + "/hosts/macbook-pro-nixvm/hardware-configuration.nix")
      (inputs.self.outPath + "/hosts/macbook-pro-nixvm/secrets.nix")
      (inputs.self.outPath + "/hosts/macbook-pro-nixvm/virtfs.nix")
    ];
  };
}

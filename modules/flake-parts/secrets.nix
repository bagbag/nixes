{ inputs, ... }:
{
  nstdl.secrets = {
    administrators.patrick.keys = {
      nixstation = {
        identity = "~/.ssh/id_ed25519";
        publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMM/o1cLFjnD1m41DE41yWySYzOjvN7MizVJLIpbhbXN patrick@nixstation";
      };
      nixbook-air = {
        identity = "~/.ssh/id_ed25519";
        publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBAZNTeHlIEMl2ILVsUjmWwptaTSSLOQRx0Xpeci562a patrick@nixbook-air";
      };
      nixmobil = {
        identity = "~/.ssh/id_ed25519";
        publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvnCyc7hK0Tb5bXujzcjF+FjpmGi4FnfD9y84RtU6ZQ patrick@nixmobil";
      };
    };
    storage = {
      mode = "local";
      root = inputs.self.outPath + "/secrets/rekeyed";
    };
    items.patrick-password-hash = {
      rekeyFile = inputs.self.outPath + "/secrets/patrick-password-hash.age";
      access.nixstation = {
        owner = "patrick";
        mode = "0400";
      };
      access.nixmobil = {
        owner = "patrick";
        mode = "0400";
      };
    };
    items.awscli-insolytix-s3-secret-key = {
      rekeyFile = inputs.self.outPath + "/secrets/awscli-insolytix-s3-secret-key.age";
      access.nixstation = {
        owner = "patrick";
        mode = "0600";
      };
      access.nixmobil = {
        owner = "patrick";
        mode = "0600";
      };
      access.nixbook-air = {
        owner = "patrick";
        mode = "0600";
      };
    };
  };
}

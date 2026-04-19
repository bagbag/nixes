let
  nixmobil = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICvnCyc7hK0Tb5bXujzcjF+FjpmGi4FnfD9y84RtU6ZQ";

  # Add other host public keys here
  # nixstation = "...";
  # nixbook-air = "...";

  keys = [
    nixmobil
    # nixstation
    # nixbook-air
  ];
in
{
  # Example rule:
  # "example-secret.age".publicKeys = keys;
}

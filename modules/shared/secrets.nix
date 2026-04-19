{ config, ... }:
{
  # This is a skeleton for secret management using agenix-rekey/ragenix.
  # Imports of this module are currently commented out in:
  # - modules/nixos/common.nix
  # - modules/darwin/common.nix

  # Example secret definition:
  # age.secrets."example-secret" = {
  #   rekeyFile = ../../secrets/example-secret.age;
  #   mode = "600";
  #   owner = config.modules.user.name;
  # };
}

{
  osConfig,
  pkgs,
  ...
}:
let
  # A small script to output the JSON format AWS CLI requires
  # Format: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-executable.html
  credentialsLoader =
    { accessKeyId, secret }:
    pkgs.writeShellScript "get-${secret}" ''
      SECRET=$(${pkgs.coreutils}/bin/cat "${osConfig.age.secrets.${secret}.path}")
      echo '{
        "Version": 1,
        "AccessKeyId": "${accessKeyId}",
        "SecretAccessKey": "'"$SECRET"'",
        "Region": "garage"
      }'
    '';
in
{
  programs.awscli = {
    enable = true;

    # This generates ~/.aws/config
    settings = {
      # Every bucket on cloud-nix01 (production, staging and their -media).
      "profile vitrass-production" = {
        region = "garage";
        endpoint_url = "https://s3.vitrass.com";
        credential_process = "${credentialsLoader {
          accessKeyId = "operator-1";
          secret = "awscli-vitrass-production-operator-s3-secret-key";
        }}";
      };
    };
  };
}

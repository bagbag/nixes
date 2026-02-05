{
  config,
  osConfig,
  pkgs,
  ...
}:
let
  secretPath = osConfig.age.secrets.awscli-insolytix-s3-secret-key.path;

  # A small script to output the JSON format AWS CLI requires
  # Format: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-executable.html
  awscliInsolytixCredentialsLoader = pkgs.writeShellScript "get-awscli-insolytix-s3-secret-key" ''
    SECRET=$(${pkgs.coreutils}/bin/cat "${secretPath}")
    echo '{
      "Version": 1,
      "AccessKeyId": "GK...",
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
      "profile garage" = {
        region = "garage";
        endpoint_url = "https://s3.insolytix.de";
        credential_process = "${awscliInsolytixCredentialsLoader}";
      };
    };
  };
}

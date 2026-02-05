{ config, ... }:
{
  age.secrets."awscli-insolytix-s3-secret-key" = {
    rekeyFile = ../../secrets/awscli-insolytix-s3-secret-key.age;
    mode = "600";
    owner = config.modules.user.name;
  };
}

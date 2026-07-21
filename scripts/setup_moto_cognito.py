"""Create a user pool + client in a moto cognito-idp server and print env exports.

Usage (inside start-cognito-test.sh):
    eval "$(uv run python scripts/setup_moto_cognito.py)"
"""

import os

import boto3

# =============================================================================
# WARNING — MOTO TEST-ONLY PASSWORD POLICY (OWASP A07, issue #24)
#
# This deliberately weak policy (8 chars, no complexity requirements) exists
# ONLY so local moto-based integration tests can create throwaway users with
# simple fixture passwords. It must NEVER be copied to a real Cognito user
# pool. Production pools must enforce a strong policy (length >= 12, upper/
# lowercase, numbers, symbols) and should be provisioned via IaC, not this
# script.
# =============================================================================
_MOTO_TEST_ONLY_PASSWORD_POLICY = {
    "PasswordPolicy": {
        "MinimumLength": 8,
        "RequireUppercase": False,
        "RequireLowercase": False,
        "RequireNumbers": False,
        "RequireSymbols": False,
    }
}


def main() -> None:
    endpoint = os.environ["COGNITO_ENDPOINT_URL"]
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client(
        "cognito-idp",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
    )
    pools = client.list_user_pools(MaxResults=10).get("UserPools", [])
    pool_id = next((p["Id"] for p in pools if p["Name"] == "algodoo-test"), None)
    if pool_id is None:
        pool_id = client.create_user_pool(
            PoolName="algodoo-test",
            AutoVerifiedAttributes=["email"],
            # Test-only weak policy — see warning block above. Never use for a
            # real user pool.
            Policies=_MOTO_TEST_ONLY_PASSWORD_POLICY,
        )["UserPool"]["Id"]
    clients = client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=10).get(
        "UserPoolClients", []
    )
    client_id = next((c["ClientId"] for c in clients if c["ClientName"] == "algodoo-web"), None)
    if client_id is None:
        client_id = client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="algodoo-web",
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )["UserPoolClient"]["ClientId"]
    print(f"export COGNITO_USER_POOL_ID={pool_id}")
    print(f"export COGNITO_CLIENT_ID={client_id}")


if __name__ == "__main__":
    main()

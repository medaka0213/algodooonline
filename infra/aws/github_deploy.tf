# GitHub Actions -> AWS via OIDC (no long-lived access keys). The deploy job in
# .github/workflows/ci.yml assumes this role on pushes to main and swaps the
# Lambda code only; infrastructure stays a manual `terraform apply`.

# IAM allows exactly one OIDC provider per issuer URL per account. If another
# stack creates it later, import it here instead of declaring a second one.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS validates GitHub's certificate chain itself; no thumbprint is needed.
}

data "aws_iam_policy_document" "github_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflow runs on the main branch of this repository (the deploy job
    # sets no `environment:`, so the subject is the ref form).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_deploy_branch}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${var.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_deploy_assume.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "github_deploy" {
  # Code swap for the one function, plus the read the deploy job needs to wait
  # for the update and to compare code hashes.
  statement {
    sid       = "DeployFunctionCode"
    actions   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
    resources = [aws_lambda_function.web.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${var.name}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

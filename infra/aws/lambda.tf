resource "random_password" "legacy_x_api_key" {
  length  = 48
  special = false
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}-web"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-web-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid = "Table"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:ConditionCheckItem",
    ]
    resources = [
      aws_dynamodb_table.main.arn,
      "${aws_dynamodb_table.main.arn}/index/*",
    ]
  }

  # Attachments only ever land under IMAGE/ and DATA/ (algodoo_data.uploads).
  statement {
    sid     = "Assets"
    actions = ["s3:PutObject", "s3:PutObjectAcl"]
    resources = [
      "arn:aws:s3:::${var.asset_bucket}/IMAGE/*",
      "arn:aws:s3:::${var.asset_bucket}/DATA/*",
    ]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name}-web"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_lambda_function" "web" {
  function_name    = "${var.name}-web"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "algodoo_web.lambda_handler.handler"
  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  memory_size      = var.lambda_memory_mb
  timeout          = 29 # HTTP API integration ceiling

  environment {
    variables = {
      APP_ENV                  = "production"
      AUTH_BACKEND             = "cognito"
      COGNITO_USER_POOL_ID     = var.cognito_user_pool_id
      COGNITO_CLIENT_ID        = aws_cognito_user_pool_client.web.id
      COGNITO_REFRESH_TTL_DAYS = tostring(var.cognito_refresh_token_days)
      LEGACY_X_API_KEY         = random_password.legacy_x_api_key.result
      DDB_TABLE_NAME           = aws_dynamodb_table.main.name
      DDB_AUTO_CREATE          = "false"
      ASSET_S3_BUCKET          = var.asset_bucket
      ASSET_PUBLIC_BASE_URL    = var.asset_public_base_url
      ASSET_S3_PUBLIC_ACL      = "true"
      ASSET_S3_AUTO_CREATE     = "false"
      SEED_DEMO_DATA           = "false"
      COOKIE_SECURE            = "true"
      MEDIA_ROOT               = "/tmp/media"
    }
  }

  depends_on = [aws_iam_role_policy.lambda, aws_cloudwatch_log_group.lambda]
}

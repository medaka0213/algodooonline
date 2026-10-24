variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "name" {
  description = "Prefix for every resource this stack creates."
  type        = string
  default     = "algodooonline"
}

variable "lambda_zip_path" {
  description = "Deployment zip built by scripts/build_lambda.sh."
  type        = string
  default     = "../../dist/lambda.zip"
}

variable "table_name" {
  description = "Single DynamoDB table (ddb_single layout)."
  type        = string
  default     = "algodoo-main"
}

variable "cognito_user_pool_id" {
  description = "Existing legacy user pool (AlgonTest). Only an app client is added to it."
  type        = string
  default     = "ap-northeast-1_pw2aWQAZZ"
}

variable "cognito_refresh_token_days" {
  type    = number
  default = 30
}

variable "asset_bucket" {
  description = "Existing public-read attachment bucket (objects are written with ACL public-read)."
  type        = string
  default     = "img.algodooonline.net"
}

variable "asset_public_base_url" {
  type    = string
  default = "https://img.algodooonline.net"
}

variable "hosted_zone_name" {
  type    = string
  default = "algodooonline.net"
}

variable "domain_names" {
  description = "Custom domains served by the HTTP API. DNS is switched by scripts/cutover_dns.sh, not here."
  type        = list(string)
  default     = ["algodooonline.net", "www.algodooonline.net"]
}

variable "lambda_memory_mb" {
  description = "More memory = more CPU = shorter cold starts; billed per GB-second only while running."
  type        = number
  default     = 1024
}

variable "throttle_rate_limit" {
  description = "Steady-state requests/second cap on the HTTP API (caps worst-case cost)."
  type        = number
  default     = 20
}

variable "throttle_burst_limit" {
  type    = number
  default = 50
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "github_repo" {
  description = "GitHub repository (owner/name) allowed to deploy through OIDC."
  type        = string
  default     = "medaka0213/algodooonline"
}

variable "github_deploy_branch" {
  description = "Only workflow runs on this branch can assume the deploy role."
  type        = string
  default     = "main"
}

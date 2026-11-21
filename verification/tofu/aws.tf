terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.22.0"
    }
  }
}

variable "region" {
  type = string
}

variable "account" {
  type = string
}

variable "run" {
  type = string
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account]
}

resource "aws_ssm_parameter" "pilot" {
  name        = "/adl-sandbox/${var.run}"
  description = "Temporary ADL runtime pilot marker"
  type        = "String"
  tier        = "Standard"
  value       = var.run
  tags        = { "adl-run" = var.run }
}

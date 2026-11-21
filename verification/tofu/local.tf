variable "run" {
  type = string
}

resource "terraform_data" "pilot" {
  input = var.run
}

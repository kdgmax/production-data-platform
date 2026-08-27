output "vpc_id" {
  description = "ID of the isolated data-platform VPC."
  value       = aws_vpc.data_platform.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs for future Airflow, ECS, or Spark workers."
  value       = aws_subnet.private[*].id
}

output "landing_bucket" {
  description = "S3 bucket for immutable landed source objects."
  value       = aws_s3_bucket.data["landing"].id
}

output "processed_bucket" {
  description = "S3 bucket for partitioned processed datasets."
  value       = aws_s3_bucket.data["processed"].id
}

output "database_endpoint" {
  description = "Private PostgreSQL endpoint."
  value       = aws_db_instance.data_platform.endpoint
}

output "database_secret_arn" {
  description = "RDS-managed Secrets Manager secret containing the master credentials."
  value       = aws_db_instance.data_platform.master_user_secret[0].secret_arn
}

output "pipeline_role_arn" {
  description = "Least-privilege IAM role for an ECS-based pipeline runtime."
  value       = aws_iam_role.pipeline.arn
}

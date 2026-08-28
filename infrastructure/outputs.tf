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

output "ecr_repository_url" {
  description = "ECR repository URL for the optional pipeline runtime."
  value       = var.enable_ecs_runtime ? aws_ecr_repository.pipeline[0].repository_url : null
}

output "ecs_cluster_name" {
  description = "ECS cluster used for on-demand pipeline tasks."
  value       = var.enable_ecs_runtime ? aws_ecs_cluster.pipeline[0].name : null
}

output "ecs_task_definition_family" {
  description = "Task definition family updated by the deployment workflow."
  value       = var.enable_ecs_runtime ? aws_ecs_task_definition.pipeline[0].family : null
}

output "ecs_runtime_security_group_id" {
  description = "No-ingress security group used by on-demand Fargate tasks."
  value       = var.enable_ecs_runtime ? aws_security_group.ecs_runtime[0].id : null
}

output "github_deploy_role_arn" {
  description = "Environment-scoped GitHub OIDC role for image deployment and task execution."
  value       = var.enable_ecs_runtime ? aws_iam_role.github_deploy[0].arn : null
}


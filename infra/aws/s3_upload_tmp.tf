# Expire the chunks of abandoned uploads. The asset bucket is managed outside this
# stack and had no lifecycle configuration when this was written, so this resource
# only adds the rules below. If someone adds other rules later, fold them in here:
# S3 keeps exactly one lifecycle configuration per bucket and this resource owns it.
#
# The bucket has versioning enabled: a delete (including the app's cleanup after
# a successful post) only adds a delete marker and keeps the data as a noncurrent
# version, so noncurrent versions must expire too, and the empty delete markers
# are swept afterwards.
resource "aws_s3_bucket_lifecycle_configuration" "upload_tmp" {
  bucket = var.asset_bucket

  rule {
    id     = "expire-upload-chunks"
    status = "Enabled"

    filter {
      prefix = "${var.upload_tmp_prefix}/"
    }

    expiration {
      days = var.upload_tmp_expire_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "sweep-upload-chunk-delete-markers"
    status = "Enabled"

    filter {
      prefix = "${var.upload_tmp_prefix}/"
    }

    expiration {
      expired_object_delete_marker = true
    }
  }
}

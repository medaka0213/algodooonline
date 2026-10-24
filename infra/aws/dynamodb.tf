# Mirrors ddb_single Table.create_table() (pk/sk + 4 GSIs) but on-demand, so an
# idle table costs storage only. The app runs with DDB_AUTO_CREATE=false.
resource "aws_dynamodb_table" "main" {
  name                        = var.table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = true

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "data"
    type = "S"
  }
  attribute {
    name = "data-n"
    type = "N"
  }
  attribute {
    name = "data-b"
    type = "B"
  }

  global_secondary_index {
    name            = "RangeIndex"
    hash_key        = "sk"
    range_key       = "pk"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "DataSearchIndex"
    hash_key        = "sk"
    range_key       = "data"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "NumDataSearchIndex"
    hash_key        = "sk"
    range_key       = "data-n"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "BinDataSearchIndex"
    hash_key        = "sk"
    range_key       = "data-b"
    projection_type = "ALL"
  }

  # Billed per GB stored (the table is well under 1 MB).
  point_in_time_recovery {
    enabled = true
  }
}

We should save a list of all user requests (non duplicates) in the workflow json file.

Not templatized since that can be achieved by deteministically parse the user input (based on the workflow inputs) if that is needed.

We can use this data when for for example repairing workflows (to understand user intent)

We are currently saving this into rich metadata:

    ,
    "execution_count": 2,
    "last_execution_timestamp": "2025-09-29T13:06:43.803416",
    "last_execution_success": true,
    "last_execution_params": {
      "message_count": 10,
      "slack_channel_id": "C09C16NAU5B",
      "google_sheets_id": "1rWrTSw0XT1D-e5XsrerWgupqEs-1Mtj-fT6e_kKYjek",
      "sheet_name": "Sheet1",
      "__verbose__": false
    }

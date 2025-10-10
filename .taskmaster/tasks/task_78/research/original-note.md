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


---

Additional insights:

1.

this will allow users to say things like:

do the slack workflow with my usual params

this is possible because we will save the params used in the workflow json file in combination with the user request.

2.

This will also help the workflow discovery (discovery node) be able to make better decisions.

3.

Secutiry concerns: user inputs that is api keys and such should NEVER be saved in the workflow json file. We might need a way to mark these inputs as sensitive by adding a new field to the input object?
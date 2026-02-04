# Batch Test Parallel

Fetch users from an API and greet each one in parallel using batch processing.

## Steps

### fetch_users

Fetch a list of users from JSONPlaceholder API.

- type: http
- url: https://jsonplaceholder.typicode.com/users
- method: GET

### greet_users

Greet each user by name (parallel).

- type: shell

```yaml batch
items: ${fetch_users.response}
as: user
parallel: true
max_concurrent: 5
```

```shell command
echo "Hello, ${user.name}!"
```

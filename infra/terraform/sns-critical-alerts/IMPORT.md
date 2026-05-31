# Import the SNS critical-alerts stack

```bash
cd infra/terraform/sns-critical-alerts
terraform init

# Topic
terraform import aws_sns_topic.critical_alerts \
  arn:aws:sns:us-east-1:676433090238:aevus-critical-alerts

# Subscriptions (ARN format: <topic-arn>:<subscription-uuid>)
terraform import 'aws_sns_topic_subscription.emails["chiefegr@intrepidlogic.io"]' \
  arn:aws:sns:us-east-1:676433090238:aevus-critical-alerts:349282d5-432c-4876-bbc5-07203a5b2248

terraform import 'aws_sns_topic_subscription.emails["woody@intrepidlogic.io"]' \
  arn:aws:sns:us-east-1:676433090238:aevus-critical-alerts:66d4dd74-1d7e-4f98-9fe6-353e76c60092

# Verify
terraform plan
```

`terraform plan` should show no changes. If it wants to change the
`display_name`, check the live topic's display name and update the
.tf to match before applying (or the change is intentional — confirm).

## Subscription confirmation UUIDs

These UUIDs are stable per subscription. If you add a new subscriber:
1. `aws sns subscribe ...` from CLI to send the confirmation email
2. Subscriber clicks the confirmation link
3. `aws sns list-subscriptions-by-topic ...` to read the new UUID
4. Add the email to `subscriber_emails` in main.tf, run apply
5. Terraform will see the existing UUID matches the for_each key and
   adopt it cleanly

To remove a subscriber:
1. Remove from `subscriber_emails`
2. `terraform apply` — destroys the subscription

To replace (e.g. role change), do remove+add in two applies. Don't try
to edit the endpoint in place; AWS treats endpoint changes as a full
replace anyway.

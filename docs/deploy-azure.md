# Deploy on Azure

Everything runs in your own subscription: a Flex Consumption function app on a timer, one storage account, a Key Vault and Application Insights. You pay Azure for hosting and your Claude deployment for tokens; there is no per-order fee.

`azure/main.bicep` follows the Flex Consumption resource shape in Microsoft's documentation. It is not deployed from this repo's CI, so run `az bicep build` and a what-if before the first deployment.

## 1. Mailbox access

1. In Microsoft Entra ID, register an app (for example `orderline`) and create a client secret.
2. Add the Microsoft Graph **application** permission `Mail.ReadWrite` and grant admin consent. Reading attachments needs `Mail.Read`; marking a message read and tagging it needs write.
3. Limit the app to the order mailbox with Exchange Online RBAC for applications, so the permission does not cover every mailbox in the tenant.

## 2. Claude

Pick one:

* **Claude on Microsoft Foundry.** Deploy a Claude model in your Foundry resource. The Anthropic Python SDK's `AnthropicFoundry` client talks to `https://<resource>.services.ai.azure.com/anthropic` and reads `ANTHROPIC_FOUNDRY_API_KEY` and `ANTHROPIC_FOUNDRY_RESOURCE`. In Foundry, the `model` parameter is your **deployment name**, so set `ORDERLINE_MODEL` to it. Foundry also supports Microsoft Entra ID tokens instead of an API key. Usage is billed through your Azure subscription.
* **Claude API.** Set `ORDERLINE_PROVIDER=anthropic` and store an Anthropic API key. Requests opt in to server-side refusal fallbacks there; Foundry requests are sent without them.

## 3. Infrastructure

```bash
az group create --name orderline-rg --location eastus2
az deployment group create --resource-group orderline-rg --template-file azure/main.bicep \
  --parameters model=<deployment-name> foundryResource=<foundry-resource> \
               graphClientId=<app-client-id> graphMailbox=orders@yourcompany.com
```

Then put the two secrets in the vault the deployment created:

```bash
az keyvault secret set --vault-name <vault> --name graph-client-secret --value <secret>
az keyvault secret set --vault-name <vault> --name claude-api-key --value <key>
```

## 4. ERP reference data

Upload the nightly export to the `erp-reference` container: `customers.csv`, `ship_to.csv`, `items.csv`, `item_xref.csv`, `uom.csv`, `prices.csv` (columns as in `data/erp/`). Every run downloads the latest copy.

## 5. Publish

```bash
make azure-package
cd build/azure && func azure functionapp publish <function-app-name>
```

## 6. Where the CSVs go

Each run writes one CSV and one JSON sidecar per order to the `erp-import` container, and the batch review page to `review`. Point the ERP import at the container, or sync it to the share the import already watches. Agree the column spec with your integration partner and change `config/columns.yaml` to match; no code changes are needed.

## Schedule and time zone

`ORDERLINE_SCHEDULE` is an NCRONTAB expression with six fields, seconds first (`0 */5 * * * *` is every five minutes). Microsoft documents that `WEBSITE_TIME_ZONE` isn't supported on Linux Flex Consumption, so write schedules in UTC. The timer trigger keeps a lock in host storage, so a run never overlaps another one when the app scales out.

## Sources

* Microsoft Graph: [List messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0), [List attachments](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0)
* Azure Functions: [Timer trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-timer?pivots=programming-language-python), [Flex Consumption](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)
* Claude: [Claude in Microsoft Foundry](https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry), [Use Claude models in Foundry](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-claude)

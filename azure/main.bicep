// Orderline in the customer's own Azure subscription: a Flex Consumption function app with a
// system-assigned identity, a storage account (host storage, deployment package, ERP reference,
// ERP import, review reports, state), Key Vault for the two secrets, and Application Insights.
// No per-order fee anywhere: you pay Azure for hosting and your Claude deployment for tokens.
//
// Written against the Flex Consumption resource shape in Microsoft's docs and samples, not
// deployed from this repo's CI. Run `az bicep build --file azure/main.bicep` and a what-if
// before the first deployment.

@description('Short prefix for resource names, lowercase letters and digits.')
param prefix string = 'orderline'
param location string = resourceGroup().location
@description('NCRONTAB, six fields. Every five minutes by default.')
param schedule string = '0 */5 * * * *'
@allowed(['anthropic', 'foundry'])
param provider string = 'foundry'
@description('Claude model id (Claude API) or deployment name (Microsoft Foundry).')
param model string
param foundryResource string = ''
param graphTenantId string = subscription().tenantId
param graphClientId string
param graphMailbox string

var suffix = uniqueString(resourceGroup().id)
var storageName = take('${prefix}${suffix}', 24)
var containers = ['deployment', 'erp-reference', 'erp-import', 'review', 'orderline-state']

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource blobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in containers: {
  parent: blobService
  name: c
}]

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('${prefix}-kv-${suffix}', 24)
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-ai-${suffix}'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${prefix}-plan-${suffix}'
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource app 'Microsoft.Web/sites@2024-04-01' = {
  name: '${prefix}-${suffix}'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}deployment'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
      runtime: { name: 'python', version: '3.11' }
    }
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'ORDERLINE_SCHEDULE', value: schedule }
        { name: 'ORDERLINE_STORAGE_URL', value: storage.properties.primaryEndpoints.blob }
        { name: 'ORDERLINE_PROVIDER', value: provider }
        { name: 'ORDERLINE_MODEL', value: model }
        { name: 'ORDERLINE_EFFORT', value: 'medium' }
        { name: 'ANTHROPIC_FOUNDRY_RESOURCE', value: foundryResource }
        { name: 'ANTHROPIC_FOUNDRY_API_KEY', value: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=claude-api-key)' }
        { name: 'ANTHROPIC_API_KEY', value: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=claude-api-key)' }
        { name: 'GRAPH_TENANT_ID', value: graphTenantId }
        { name: 'GRAPH_CLIENT_ID', value: graphClientId }
        { name: 'GRAPH_CLIENT_SECRET', value: '@Microsoft.KeyVault(VaultName=${vault.name};SecretName=graph-client-secret)' }
        { name: 'GRAPH_MAILBOX', value: graphMailbox }
      ]
    }
  }
}

// Role assignments for the app's identity: blob data owner on its storage (host storage and the
// containers above), and secrets user on the vault.
var blobDataOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource storageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, app.id, blobDataOwner)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataOwner)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource vaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, app.id, keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output functionApp string = app.name
output storageAccount string = storage.name
output keyVault string = vault.name

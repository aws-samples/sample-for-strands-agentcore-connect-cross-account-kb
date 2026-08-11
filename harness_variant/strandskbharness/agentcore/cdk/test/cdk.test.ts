// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as fs from 'fs';
import * as path from 'path';
import type { AgentCoreMcp } from '@aws/agentcore-cdk';
import { AgentCoreStack, scopeMcpLambdaLogging } from '../lib/cdk-stack';

test('AgentCoreStack synthesizes with empty spec', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'TestStack', {
    spec: {
      name: 'testproject',
      version: 1,
      managedBy: 'CDK' as const,
      runtimes: [],
      memories: [],
      credentials: [],
      evaluators: [],
      onlineEvalConfigs: [],
      configBundles: [],
      policyEngines: [],
      payments: [],
      agentCoreGateways: [],
      mcpRuntimeTools: [],
      unassignedTargets: [],
      datasets: [],
      knowledgeBases: [],
    },
  });
  const template = Template.fromStack(stack);
  template.hasOutput('StackNameOutput', {
    Description: 'Name of the CloudFormation Stack',
  });
});

test('Harness synthesis is not gated by a preview environment variable', () => {
  const entrypoint = fs.readFileSync(path.join(__dirname, '../bin/cdk.ts'), 'utf8');

  expect(entrypoint).not.toContain('AGENTCORE_PREVIEW');
  expect(entrypoint).toContain('for (const entry of specAny.harnesses ?? [])');
});

test('Lambda log groups remain reusable across stack recreation', () => {
  const cdkConfig = JSON.parse(fs.readFileSync(path.join(__dirname, '../cdk.json'), 'utf8'));

  expect(cdkConfig.context['@aws-cdk/aws-lambda:useCdkManagedLogGroup']).toBe(false);
});

test('Lambda logging policies do not depend on the Lambda function resource', () => {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, 'LoggingStack');
  const fn = new lambda.Function(stack, 'ToolFunction', {
    code: lambda.Code.fromInline('def handler(event, context): return {}'),
    functionName: 'test-kb-tool',
    handler: 'index.handler',
    runtime: lambda.Runtime.PYTHON_3_14,
  });

  scopeMcpLambdaLogging({
    lambdaFunctions: new Map([['tool', fn]]),
  } as unknown as AgentCoreMcp);

  const resources = Template.fromStack(stack).toJSON().Resources;
  const loggingPolicy = Object.values(resources).find((resource: any) =>
    resource.Type === 'AWS::IAM::Policy'
      && resource.Properties.PolicyDocument.Statement.some(
        (statement: any) => statement.Sid === 'LambdaLogGroup'
      )
  ) as any;
  const statements = loggingPolicy.Properties.PolicyDocument.Statement;

  expect(JSON.stringify(statements)).toContain('/aws/lambda/test-kb-tool');
  expect(JSON.stringify(statements)).not.toContain('"Ref":"ToolFunction');
});

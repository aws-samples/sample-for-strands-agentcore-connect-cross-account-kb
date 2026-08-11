// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';

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

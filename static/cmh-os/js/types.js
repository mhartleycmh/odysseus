// Data contracts shared by the live and demo data sources. Types only: this
// module exports nothing at runtime. See integrations/cmh/docs/ARCHITECTURE.md §4.

/**
 * @typedef {'real'|'demo'} Origin
 * @typedef {'ok'|'warn'|'risk'|'idle'|'live'} Tone
 * @typedef {'lectura'|'escritura'|'admin'} PermissionLevel
 * @typedef {'active'|'paused'|'running'|'error'} AgentStatus
 * @typedef {'alto'|'medio'|'bajo'} RiskLevel
 * @typedef {'baja'|'media'|'alta'} Priority
 */

/**
 * @typedef {Object} AgentCapability
 * @property {string} id
 * @property {string} label
 * @property {string} description
 */

/**
 * @typedef {Object} Agent
 * @property {string} id
 * @property {string} name
 * @property {string} role
 * @property {string|null} projectId
 * @property {AgentStatus} status
 * @property {string|null} model
 * @property {string[]} allowedTools
 * @property {string|null} workspace
 * @property {PermissionLevel} permissionLevel
 * @property {string} instructions
 * @property {number} instructionsVersion
 * @property {string|null} taskId
 * @property {AgentCapability[]} capabilities
 * @property {string} domain
 * @property {Origin} origin
 */

/**
 * @typedef {Object} AgentInput
 * @property {string} name
 * @property {string} role
 * @property {string|null} projectId
 * @property {string|null} model
 * @property {string[]} allowedTools
 * @property {string|null} workspace
 * @property {string} instructions
 * @property {string|null} taskId
 */

/**
 * @typedef {Object} Project
 * @property {string} id
 * @property {string} name
 * @property {string} status
 * @property {Origin} origin
 */

/**
 * @typedef {Object} ModelProvider
 * @property {string} id
 * @property {string} name
 * @property {string} baseUrl
 * @property {'online'|'offline'|'unknown'} status
 * @property {boolean} hasKey
 * @property {string|null} keyFingerprint
 * @property {boolean|null} supportsTools
 * @property {string[]} models
 * @property {string} category
 * @property {Origin} origin
 */

/**
 * @typedef {'archivos'|'shell'|'web'|'mcp'|'memoria'|'comunicacion'} ToolCategory
 * @typedef {Object} Tool
 * @property {string} id
 * @property {string} name
 * @property {ToolCategory} category
 * @property {string} description
 * @property {RiskLevel} risk
 * @property {boolean} enabled
 * @property {boolean} readOnly
 * @property {boolean} requiresApproval
 * @property {string|null} serverId
 * @property {number} usageCount
 * @property {string[]} usedBy
 * @property {Origin} origin
 */

/**
 * @typedef {Object} MCPServer
 * @property {string} id
 * @property {string} name
 * @property {string} transport
 * @property {'connected'|'disconnected'|'error'|'needs_auth'} status
 * @property {number} toolCount
 * @property {number} enabledToolCount
 * @property {string[]} envKeys Names only; values never leave the service layer.
 * @property {string|null} error
 * @property {Origin} origin
 */

/**
 * @typedef {Object} WorkflowStep
 * @property {string} key
 * @property {string} agentId
 * @property {string[]} dependsOn
 * @property {string[]} independentOf
 * @property {boolean} requiresApproval
 */

/**
 * @typedef {Object} Workflow
 * @property {string} id
 * @property {string} name
 * @property {string} projectId
 * @property {number} version
 * @property {string} description
 * @property {WorkflowStep[]} steps
 * @property {Origin} origin
 */

/**
 * @typedef {'pending'|'running'|'waiting_approval'|'completed'|'error'|'interrupted'|'paused'|'rejected'} ExecutionStatus
 * @typedef {'pending'|'running'|'waiting_approval'|'completed'|'error'|'interrupted'|'rejected'} StepStatus
 */

/**
 * @typedef {Object} ToolCall
 * @property {string} tool
 * @property {'running'|'ok'|'error'} status
 * @property {number|null} durationSeconds
 */

/**
 * @typedef {Object} ExecutionStep
 * @property {string} key
 * @property {string} agentId
 * @property {string} agentName
 * @property {StepStatus} status
 * @property {string|null} model
 * @property {string[]} dependencies
 * @property {boolean} requiresApproval
 * @property {string|null} error
 * @property {string|null} startedAt
 * @property {string|null} finishedAt
 * @property {ToolCall[]} tools
 * @property {number} tokensIn
 * @property {number} tokensOut
 */

/**
 * @typedef {Object} Artifact
 * @property {string} id
 * @property {string} stepKey
 * @property {string} model
 * @property {string} content
 */

/**
 * @typedef {Object} ExecutionLimits
 * @property {number|null} maxIterations
 * @property {number|null} timeoutSeconds
 * @property {number|null} budgetUsd
 * @property {boolean} enforced False when the backend does not apply them.
 */

/**
 * @typedef {Object} ExecutionUsage
 * @property {number} tokensIn
 * @property {number} tokensOut
 * @property {number|null} costUsd
 * @property {number} iterations
 * @property {number} elapsedSeconds
 * @property {boolean} measured False until run events were seen: zeros are then unknown, not real.
 */

/**
 * @typedef {Object} Execution
 * @property {string} id
 * @property {string} workflowId
 * @property {string} workflowName
 * @property {string} projectId
 * @property {string} objective
 * @property {Priority} priority
 * @property {string|null} responsibleAgentId
 * @property {ExecutionStatus} status
 * @property {string} createdAt
 * @property {string|null} startedAt
 * @property {string|null} finishedAt
 * @property {ExecutionLimits} limits
 * @property {ExecutionUsage} usage
 * @property {ExecutionStep[]} steps
 * @property {Artifact[]} artifacts
 * @property {string|null} finalAnswer
 * @property {string|null} error
 * @property {number} attempt
 * @property {Origin} origin
 */

/**
 * @typedef {Object} ExecutionInput
 * @property {string} workflowId
 * @property {string} objective
 * @property {Priority} priority
 * @property {string|null} responsibleAgentId
 * @property {number|null} maxIterations
 * @property {number|null} timeoutSeconds
 * @property {number|null} budgetUsd
 */

/**
 * @typedef {Object} RunEvent
 * @property {number} seq
 * @property {string} kind
 * @property {string|null} stepKey
 * @property {Record<string, unknown>} payload
 * @property {string} at
 */

/**
 * @typedef {'trabajo'|'episodica'|'semantica'} MemoryKind
 * @typedef {Object} MemoryRecord
 * @property {string} id
 * @property {MemoryKind} kind
 * @property {string} title
 * @property {string} content
 * @property {string} source
 * @property {string} createdAt
 * @property {number} relevance 0..1
 * @property {string[]} tags
 * @property {boolean} archived
 * @property {boolean} archivable
 * @property {string|null} path
 * @property {Origin} origin
 */

/**
 * @typedef {'paso'|'memoria'|'herramienta'} ApprovalKind
 * @typedef {'pendiente'|'aprobada'|'rechazada'} ApprovalStatus
 * @typedef {Object} ApprovalRequest
 * @property {string} id
 * @property {ApprovalKind} kind
 * @property {string} title
 * @property {string} requestedBy
 * @property {string|null} agentId
 * @property {string|null} executionId
 * @property {string|null} stepKey
 * @property {string|null} proposalId
 * @property {string} action
 * @property {Record<string, string>} args
 * @property {string} impact
 * @property {string} rejectEffect What "reject" actually does in this backend.
 * @property {RiskLevel} risk
 * @property {ApprovalStatus} status
 * @property {string} createdAt
 * @property {string|null} decidedAt
 * @property {string|null} decidedBy
 * @property {string|null} justification
 * @property {string|null} diff
 * @property {Origin} origin
 */

/**
 * @typedef {Object} Span
 * @property {string} id
 * @property {string} name
 * @property {'paso'|'herramienta'|'modelo'|'aprobacion'} kind
 * @property {string|null} stepKey
 * @property {number} startMs
 * @property {number} durationMs
 * @property {'ok'|'error'|'running'} status
 * @property {number} tokens
 */

/**
 * @typedef {Object} Trace
 * @property {string} id
 * @property {string} executionId
 * @property {string} name
 * @property {ExecutionStatus} status
 * @property {string} startedAt
 * @property {number} durationMs
 * @property {number} tokensIn
 * @property {number} tokensOut
 * @property {number|null} costUsd
 * @property {number} errors
 * @property {string[]} agents
 * @property {boolean} measured False when built without events (live list): show "—", not 0.
 * @property {Span[]} spans
 * @property {Origin} origin
 */

/**
 * @typedef {Object} EvaluationCase
 * @property {string} id
 * @property {string} input
 * @property {string} expected
 * @property {'ok'|'fallo'|'pendiente'} result
 * @property {number|null} score
 */

/**
 * @typedef {Object} Evaluation
 * @property {string} id
 * @property {string} name
 * @property {string} dataset
 * @property {string} target
 * @property {string} metric
 * @property {EvaluationCase[]} cases
 * @property {number|null} score
 * @property {number|null} baselineScore
 * @property {string|null} runAt
 * @property {{runAt: string, score: number}[]} history
 * @property {Origin} origin
 */

/**
 * @typedef {Object} Role
 * @property {string} id
 * @property {string} name
 * @property {string} description
 * @property {string[]} permissions
 * @property {number} members
 * @property {Origin} origin
 */

/**
 * @typedef {Object} SecurityPolicy
 * @property {string} id
 * @property {string} name
 * @property {string} scope
 * @property {'permitir'|'denegar'|'aprobar'} effect
 * @property {string} description
 * @property {'backend'|'interfaz'|'demo'} enforcedBy
 * @property {Origin} origin
 */

/**
 * @typedef {Object} SecretRef
 * @property {string} id
 * @property {string} name
 * @property {string} owner
 * @property {boolean} configured
 * @property {string|null} fingerprint
 * @property {Origin} origin
 */

/**
 * @typedef {Object} UserSession
 * @property {string} id
 * @property {string} user
 * @property {string} startedAt
 * @property {string} lastSeen
 * @property {boolean} current
 * @property {Origin} origin
 */

/**
 * @typedef {Object} AuditEvent
 * @property {string} id
 * @property {string} at
 * @property {string} actor
 * @property {string} action
 * @property {string} target
 * @property {'ok'|'rechazado'|'error'} outcome
 * @property {string} detail
 * @property {'servidor'|'local'|'demo'} recordedIn
 */

/**
 * @typedef {Object} SecurityOverview
 * @property {Role[]} roles
 * @property {SecurityPolicy[]} policies
 * @property {SecretRef[]} secrets
 * @property {UserSession[]} sessions
 * @property {AuditEvent[]} audit
 */

/**
 * @typedef {Object} SystemService
 * @property {string} id
 * @property {string} name
 * @property {Tone} tone
 * @property {string} detail
 * @property {Origin} origin
 */

/**
 * @typedef {Object} Capabilities Which domains the live backend serves.
 * @property {boolean} agents
 * @property {boolean} executions
 * @property {boolean} executionLimits
 * @property {boolean} approvals
 * @property {boolean} memory
 * @property {boolean} memoryArchive
 * @property {boolean} tools
 * @property {boolean} traces
 * @property {boolean} evaluations
 * @property {boolean} security
 * @property {boolean} providers
 * @property {boolean} chatModel
 */

/**
 * @typedef {Object} RunStreamHandlers
 * @property {(event: RunEvent) => void} onEvent
 * @property {(state: 'open'|'reconnecting'|'closed') => void} [onState]
 */

/**
 * @typedef {Object} RunEventStream
 * @property {() => void} close
 */

/**
 * @typedef {'aprobar'|'rechazar'} Decision
 */

/**
 * @typedef {Object} DataSource
 * @property {Origin} mode
 * @property {Capabilities} capabilities
 * @property {() => Promise<Project[]>} listProjects
 * @property {() => Promise<Agent[]>} listAgents
 * @property {(id: string) => Promise<Agent>} getAgent
 * @property {(input: AgentInput, id?: string) => Promise<Agent>} saveAgent
 * @property {(id: string, status: 'active'|'paused') => Promise<Agent>} setAgentStatus
 * @property {() => Promise<Workflow[]>} listWorkflows
 * @property {() => Promise<Execution[]>} listExecutions
 * @property {(id: string) => Promise<Execution>} getExecution
 * @property {(input: ExecutionInput) => Promise<Execution>} createExecution
 * @property {(id: string) => Promise<Execution>} cancelExecution
 * @property {(id: string, limits?: Partial<Pick<ExecutionLimits, 'maxIterations'|'timeoutSeconds'|'budgetUsd'>>) => Promise<Execution>} retryExecution
 * @property {(id: string, handlers: RunStreamHandlers) => RunEventStream} openRunStream
 * @property {() => Promise<ApprovalRequest[]>} listApprovals
 * @property {(id: string, decision: Decision, justification: string, actor: string) => Promise<ApprovalRequest>} decideApproval
 * @property {() => Promise<MemoryRecord[]>} listMemory
 * @property {(id: string) => Promise<MemoryRecord>} readMemory Loads content when the list returned it empty.
 * @property {(id: string) => Promise<MemoryRecord>} archiveMemory
 * @property {() => Promise<Tool[]>} listTools
 * @property {() => Promise<MCPServer[]>} listMcpServers
 * @property {() => Promise<Trace[]>} listTraces
 * @property {(executionId: string) => Promise<Trace>} getTrace
 * @property {() => Promise<Evaluation[]>} listEvaluations
 * @property {(id: string) => Promise<Evaluation>} runEvaluation
 * @property {() => Promise<SecurityOverview>} getSecurity
 * @property {() => Promise<ModelProvider[]>} listProviders
 * @property {() => Promise<SystemService[]>} getServices
 * @property {(message: string, endpointId: string, model: string) => Promise<string>} askModel
 */

/**
 * @typedef {Object} FeatureFlags
 * @property {boolean} chatModel Free-text chat questions go to the configured model.
 * @property {boolean} simulateFailures Demo reads fail transiently (every other call).
 * @property {boolean} evaluations Show the evaluations module.
 */

/**
 * @typedef {Object} Prefs
 * @property {'system'|'light'|'dark'} theme
 * @property {'system'|'reduced'|'full'} motion
 * @property {'auto'|'demo'} mode
 * @property {string} language
 * @property {FeatureFlags} flags
 * @property {{maxIterations: number, timeoutSeconds: number, budgetUsd: number}} limits
 * @property {{endpointId: string, model: string}|null} chatModel
 * @property {string} actor Name recorded in the local audit trail.
 */

/**
 * @typedef {Object} AppContext
 * @property {DataSource} source
 * @property {Origin} mode
 * @property {'forzado'|'sin_sesion'|'sin_permiso'|'sin_servidor'|null} reason
 * @property {() => Prefs} prefs
 * @property {(patch: Partial<Prefs>) => void} setPrefs
 * @property {(hash: string) => void} navigate
 * @property {() => void} refreshCounts
 * @property {(executionId: string) => Promise<boolean>} confirmStop
 * @property {() => boolean} reducedMotion
 */

export {};

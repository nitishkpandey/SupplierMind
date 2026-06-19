export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "procurement_manager" | "analyst";
}

export interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  clearAuth: () => void;
}

export type SearchScope = 'approved_only' | 'both';
export type QueryStatus = "pending" | "processing" | "completed" | "failed" | "needs_clarification";
export type SupplierStatus = 'approved' | 'saved' | 'discovered' | 'pending_review' | 'rejected';

export interface ParsedConstraints {
  category?: string;
  category_hint?: string;
  product_type?: string;
  product_keywords?: string[];
  industry_context?: string;
  buyer_intent?: string;
  location_name?: string;
  location_city?: string;
  location_country?: string;
  location_region?: string;
  location_lat?: number;
  location_lng?: number;
  location_radius_km?: number;
  certifications?: string[];
  industry_typical_certs?: string[];
  capacity_min?: number;
  capacity_unit?: string;
  lead_time_max_days?: number;
  ranking_preferences?: string[];
  unsupported_preferences?: string[];
  query_type?: "geographic_priority" | "compliance_critical" | "capability_match" | "general" | string;
  complexity?: string;
  original_language?: string;
}

export type ComplianceStatus = "PASS" | "FAIL" | "PARTIAL";
export type ComplianceMatrix = Record<string, ComplianceStatus>;

export interface SourceCitation {
  url?: string;
  source?: string;
  source_phrase?: string;
  confidence?: number;
  formatted_address?: string;
  certifications?: Record<string, SourceCitation>;
}

// Structured, template-based explanation assembled from validated data. Numbers
// trace to the supplier DB row and do not come from LLM-generated prose.
export interface ExplanationDetail {
  match_reasons: string[];
  concerns: string[];
  facts: {
    capacity: string;
    lead_time: string;
    certifications: string[];
    location: string;
    tier: string;
  };
  summary: string;
}

export interface QueryResult {
  rank: number;
  supplier_id: string;
  supplier_name: string;
  supplier_city: string | null;
  supplier_country: string | null;
  supplier_lat: number | null;
  supplier_lng: number | null;
  supplier_certifications: string[] | null;
  supplier_capacity_value: number | null;
  supplier_capacity_unit: string | null;
  supplier_lead_time_days: number | null;
  supplier_website: string | null;
  supplier_source: string | null;
  supplier_source_url?: string | null;
  supplier_source_citations?: Record<string, SourceCitation> | null;
  supplier_certification_details?: Record<string, unknown> | null;
  supplier_status: SupplierStatus | null;
  tier: Exclude<SupplierStatus, 'rejected'> | null;
  // Present only when sanctions screening could not complete.
  sanctions_status?: 'pending_review' | null;
  total_score: number;
  constraint_score: number;
  semantic_score: number;
  proximity_score: number | null;
  completeness_score: number;
  preference_score?: number;
  compliance_matrix: ComplianceMatrix;
  explanation: string;
  explanation_detail: ExplanationDetail | null;
  distance_km: number | null;
  // Manager rationale, only present on approved/rejected suppliers.
  approval_justification?: string | null;
  approval_action?: 'approved' | 'rejected' | null;
  approval_decided_at?: string | null;
}

export interface Supplier {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  country: string | null;
  city: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  certifications: string[] | null;
  capacity_value: number | null;
  capacity_unit: string | null;
  lead_time_days: number | null;
  website: string | null;
  contact_email: string | null;
  source: string | null;
  status: SupplierStatus;
  source_url: string | null;
  source_citations: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
}

export interface QueryResponse {
  id: string;
  raw_query: string;
  status: QueryStatus;
  detected_language?: string;
  parsed_constraints?: ParsedConstraints;
  execution_time_ms?: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
  results?: QueryResult[];
}

export interface QueryWithResults extends QueryResponse {
  results: QueryResult[];
}

export interface AuditEntry {
  agent_name: string;
  action: string;
  reasoning?: string | null;
  input_snapshot?: Record<string, unknown> | null;
  output_snapshot?: { summary?: string; [key: string]: unknown } | null;
  duration_ms?: number | null;
  created_at?: string;
}

export interface SSEEvent {
  type?: "agent_update" | "complete" | "error" | "needs_clarification" | string;
  agent?: string;
  status?: string;
  message?: string;
  duration_ms?: number;
  query_id?: string;
  result_count?: number;
  execution_time_ms?: number;
}

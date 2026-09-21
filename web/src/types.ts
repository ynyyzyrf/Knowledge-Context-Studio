export interface Membership {
  tenant_id: string;
  name: string;
  role: "tenant_admin" | "editor" | "viewer";
}
export interface Profile {
  person: { id: string; email: string };
  memberships: Membership[];
  csrf_token: string;
}
export interface Entity {
  id: string;
  name: string;
  active: boolean;
}
export interface Space extends Entity {
  sync_state: string;
}
export interface Person {
  person_id: string;
  email: string;
  role: string;
  active: boolean;
}
export interface Credential {
  id: string;
  created_at: number;
  expires_at: number;
  revoked_at: number | null;
  subject_ids: string[];
}
export interface Issued {
  id: string;
  token: string;
  expires_at: number;
}
export interface Job {
  id: string;
  session_id: string;
  subject_id: string;
  state: string;
  attempt: number;
  error_code: string | null;
  updated_at: number;
  request_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
}
export interface Candidate {
  id: string;
  content: string;
  status: string;
  version: number;
  source_message_ids: string[];
}
export interface Memory extends Candidate {
  agent_id: string;
  subject_id: string;
  publication: { id: string; state: string; error_code: string | null };
}
export interface SourceMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
}
export interface Provenance {
  messages: SourceMessage[];
  revisions?: {
    version: number;
    status: string;
    content: string | null;
    reason: string;
    actor_id: string;
    created_at: number;
  }[];
}
export interface Audit {
  id: string;
  action: string;
  actor_id: string;
  target_id: string;
  created_at: number;
  request_id: string;
  details: Record<string, unknown>;
}
export interface Machine {
  tenant_id: string;
  agent_id: string;
  credential_id: string;
  subject_ids: string[];
  space_ids: string[];
}
export interface Conversation {
  id: string;
  subject_id: string;
  created_at: number;
  message_count: number;
}
export interface Message {
  id: string;
  message_id: string;
  sequence: number;
  role: string;
  content: string;
}
export interface Items<T> {
  items: T[];
}

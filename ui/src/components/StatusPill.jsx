import Icon from "./Icon";
import { deriveStatementStatus } from "../statementLanguage";

/** StatusPill — the compact form of deriveStatementStatus's business
 * vocabulary (brief §15), for table rows where a full StatementCard would
 * be too heavy. */
export default function StatusPill({ doc }) {
  const status = deriveStatementStatus(doc);
  return (
    <span className={`status-pill ${status.className}`}>
      <Icon name={status.icon} size={11} />
      {status.label}
    </span>
  );
}

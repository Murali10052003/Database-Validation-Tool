import { LockKeyhole } from "lucide-react";
import type { ValidationCheck, ValidationProfileName } from "../../api/types";
import { presetChecks, VALIDATION_CHECKS } from "./validationSelection";

interface Props {
  value: ValidationProfileName;
  selected: ValidationCheck[];
  onChange: (value: ValidationProfileName, checks: ValidationCheck[]) => void;
}

export function ProfileSelector({ value, selected, onChange }: Props) {
  return <section className="validation-picker" aria-label="Validation checks">
    <div className="validation-picker__head"><h3>Validation checks</h3><span>{selected.length} of {VALIDATION_CHECKS.length} selected</span></div>
    <div className="validation-presets" role="radiogroup" aria-label="Validation preset">
      {(["quick", "standard", "full", "custom"] as const).map(profile => <label key={profile}>
        <input type="radio" name="validation-profile" value={profile} checked={value === profile} onChange={() => onChange(profile, profile === "custom" ? selected : presetChecks(profile))} />
        <span>{profile === "quick" ? "Quick checks" : profile[0].toUpperCase() + profile.slice(1)}</span>
      </label>)}
    </div>
    <div className="validation-required"><span><LockKeyhole size={13} />Connectivity required</span><span><LockKeyhole size={13} />Discovery required</span></div>
    <div className="validation-checks">{VALIDATION_CHECKS.map(check => <label key={check.id}>
      <input type="checkbox" checked={selected.includes(check.id)} onChange={event => onChange("custom", event.target.checked ? [...selected, check.id] : selected.filter(id => id !== check.id))} />{check.label}
    </label>)}</div>
    {!selected.length && <p role="status">Select at least one validation check.</p>}
  </section>;
}

(() => {
  const form = document.getElementById("dynamicResponseForm");
  if (!form) return;
  const fields = [...form.querySelectorAll(".dynamic-response-field")];
  const byKey = new Map(fields.map(field => [field.dataset.fieldKey, field]));

  const fieldValue = field => {
    if (!field || field.classList.contains("d-none")) return "";
    const checked = [...field.querySelectorAll('input[type="checkbox"]:checked')];
    if (field.querySelector('input[type="checkbox"]')) return checked.map(input => input.value);
    const control = field.querySelector("input, select, textarea");
    return control ? control.value : "";
  };

  const matches = field => {
    const sourceKey = field.dataset.conditionSource;
    if (!sourceKey) return true;
    const actual = fieldValue(byKey.get(sourceKey));
    const expected = field.dataset.conditionValue || "";
    const operator = field.dataset.conditionOperator;
    if (operator === "not_empty") return Array.isArray(actual) ? actual.length > 0 : actual !== "";
    if (Array.isArray(actual)) {
      const contains = actual.includes(expected);
      return operator === "not_equals" ? !contains : contains;
    }
    if (operator === "equals") return actual === expected;
    if (operator === "not_equals") return actual !== expected;
    if (operator === "contains") return actual.toLocaleLowerCase("tr").includes(expected.toLocaleLowerCase("tr"));
    return false;
  };

  const sync = () => {
    fields.forEach(field => {
      const visible = matches(field);
      field.classList.toggle("d-none", !visible);
      field.setAttribute("aria-hidden", visible ? "false" : "true");
      field.querySelectorAll("input, select, textarea").forEach(control => { control.disabled = !visible; });
    });
  };
  form.addEventListener("input", sync);
  form.addEventListener("change", sync);
  sync();
})();

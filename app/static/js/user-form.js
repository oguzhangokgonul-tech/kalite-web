(() => {
  const form = document.getElementById('userForm');
  if (!form) return;
  const password = form.elements.password;
  const passwordError = document.getElementById('passwordError');
  const summary = document.getElementById('userFormError');
  const toggle = document.getElementById('togglePassword');
  const serverErrors = new Map();
  form.querySelectorAll('[data-server-error]').forEach(feedback => {
    const field = form.elements[feedback.dataset.serverError];
    if (!field) return;
    serverErrors.set(field, feedback.textContent.trim());
    field.classList.add('is-invalid');
    field.setAttribute('aria-invalid', 'true');
    const describedBy = new Set((field.getAttribute('aria-describedby') || '').split(' ').filter(Boolean));
    describedBy.add(feedback.id);
    field.setAttribute('aria-describedby', [...describedBy].join(' '));
  });

  function passwordMessage() {
    if (!password.value) return password.required ? 'Şifre girin.' : '';
    // Count code points like Python's len(), including pasted passwords.
    const length = [...password.value].length;
    if (length < password.minLength) return `Şifre en az ${password.minLength} karakter olmalıdır.`;
    if (length > password.maxLength) return `Şifre en fazla ${password.maxLength} karakter olabilir.`;
    return '';
  }

  function validatePassword(showError) {
    const validationMessage = passwordMessage();
    const message = serverErrors.get(password) || validationMessage;
    password.setCustomValidity(validationMessage);
    passwordError.textContent = showError ? message : '';
    passwordError.classList.toggle('d-block', showError && !!message);
    password.classList.toggle('is-invalid', showError && !!message);
    password.setAttribute('aria-invalid', String(showError && !!message));
  }

  function showErrors() {
    const invalid = [...form.elements].filter(field => field.willValidate && (!field.validity.valid || serverErrors.has(field)));
    summary.replaceChildren();
    summary.hidden = !invalid.length;
    if (invalid.length) summary.append('Kaydedilmedi. Kontrol edin: ');
    for (const field of form.elements) {
      if (!field.willValidate || !field.id) continue;
      const failed = invalid.includes(field);
      field.classList.toggle('is-invalid', failed);
      field.setAttribute('aria-invalid', String(failed));
      let feedback = document.getElementById(`${field.id}Error`);
      if (!feedback && failed) {
        feedback = document.createElement('div');
        feedback.id = `${field.id}Error`;
        feedback.className = 'invalid-feedback';
        field.insertAdjacentElement('afterend', feedback);
        field.setAttribute('aria-describedby', [field.getAttribute('aria-describedby'), feedback.id].filter(Boolean).join(' '));
      }
      if (feedback) {
        feedback.textContent = failed ? (serverErrors.get(field) || field.validationMessage) : '';
        feedback.classList.toggle('d-block', failed);
      }
      if (failed) {
        const link = document.createElement('a');
        link.href = `#${field.id}`;
        link.className = 'text-danger me-2';
        link.textContent = field.labels?.[0]?.textContent.trim() || field.name;
        link.addEventListener('click', event => { event.preventDefault(); field.focus(); });
        summary.append(link);
      }
    }
  }

  form.addEventListener('invalid', event => {
    const field = event.target;
    field.classList.add('is-invalid');
    field.setAttribute('aria-invalid', 'true');
    if (field === password) validatePassword(true);
    showErrors();
  }, true);
  form.addEventListener('input', event => {
    const field = event.target;
    serverErrors.delete(field);
    if (field === password) validatePassword(true);
    else if (field.validity?.valid) {
      field.classList.remove('is-invalid');
      field.removeAttribute('aria-invalid');
    }
    if (!summary.hidden) showErrors();
  });
  form.addEventListener('submit', event => {
    validatePassword(true);
    if (!form.reportValidity()) event.preventDefault();
  });
  password.addEventListener('blur', () => validatePassword(true));
  toggle.hidden = false;
  toggle.addEventListener('click', () => {
    const reveal = password.type === 'password';
    password.type = reveal ? 'text' : 'password';
    const label = reveal ? 'Şifreyi gizle' : 'Şifreyi göster';
    toggle.setAttribute('aria-pressed', String(reveal));
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
    toggle.querySelector('i').className = reveal ? 'bi bi-eye-slash' : 'bi bi-eye';
  });
})();

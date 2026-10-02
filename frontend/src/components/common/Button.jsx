import React from 'react';
import './Button.css';

const Button = ({ children, onClick, type = 'button', variant = 'primary', className = '', style = {} }) => {
  return (
    <button
      type={type}
      className={`btn btn-${variant} ${className}`}
      onClick={onClick}
      style={style}
    >
      {children}
    </button>
  );
};

export default Button;

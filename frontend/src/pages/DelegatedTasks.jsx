import React from 'react';
import TaskListView from '../components/tasks/TaskListView';

const DelegatedTasks = () => (
  <TaskListView
    scope="delegated"
    heading="Delegated Tasks"
    subheading="Tasks you created and assigned to others"
    emptyMessage="You haven't delegated any tasks yet."
    splitByRecurrence
  />
);

export default DelegatedTasks;

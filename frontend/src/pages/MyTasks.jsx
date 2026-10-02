import React from 'react';
import TaskListView from '../components/tasks/TaskListView';

const MyTasks = () => (
  <TaskListView
    scope="my"
    heading="My Tasks"
    subheading="Tasks assigned to you"
    emptyMessage="No tasks assigned to you yet."
    splitByRecurrence
  />
);

export default MyTasks;
